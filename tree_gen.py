# Filename: tree_gen.py
# Author:   Stefan Manolache
# This script is used to generate a semi-realistic tree model, together with an
# animation of its growth over its lifespan (including leaf growth and decay,
# flower blooming). 

#temp
ITERATIONS = 3

TIME_INTERVAL = 5 # how often to update simulation

import math
import random
import bpy
import numpy

from mathutils import Vector, Matrix, Euler

from typing import NamedTuple, List

# Random stuff :)
#---------------------------------------------------------------------------------

# Represents a random 1D value based on an underlying normal distribution
class RandomValue(NamedTuple):
    mean: float
    stddev: float
        
    # get deterministic value
    def get(self):
        return numpy.random.normal(self.mean, self.stddev, None)
    
RV = RandomValue

# Represents a mesh which can vary in appearance
class RandomMesh:
    def __init__(self, meshNames):
        # all possible meshes 
        self.meshes = []
        for name in meshNames:
            self.meshes.append(bpy.data.objects[name])
            
    # get deterministic mesh
    def get(self):
        # choose a mesh uniformly at random
        initMesh = random.choice(self.meshes)
        
        mesh = initMesh.copy()
        
        # important, so that mesh data is not linked to the original
        mesh.data = initMesh.data.copy()
        bpy.context.collection.objects.link(mesh)
        return mesh


# Tree part templates
#---------------------------------------------------------------------------------

# Production rule for a stem segment
class StemTemplate(NamedTuple):
    lengthRatioR: RV # how much the stem should grow/shrink in relation to the previous one


# Production rule for a bud 
# This does not directly include what the bud could grow into
# Instead, that is encoded in the index variable
# see Diagram 1 for angle explanation
class BudTemplate(NamedTuple):
    index: int # bud type index
    brcAngleR: RV  # branching angle
    divAngleR: RV  # divergence angle
    rollAngleR: RV # roll angle
    
    
# Bud Logic  
#---------------------------------------------------------------------------------    
    
# Represents one possible growth result of a bud
class BudRule(NamedTuple):
    stemT: StemTemplate 
    apiBudT: BudTemplate # apical bud
    axiBudTs: List[BudTemplate] # axillary buds
         
    
# Describes what a specific bud type can grow into
# This class is tightly-coupled with BudCollection 
# Instances should only be created by using BudCollection.add
# (not sure how to enforce this -- my python expertise -> 0
class BudType:
    def __init__(self, budRules, weights):
        self.budRules = budRules
        self.weights = weights
    
    # Apply one of the rules (based on the probability distribution)
    # Return a stem template and a list of axillary bud templates
    def sprout(self):
        rule = random.choices(self.budRules, self.weights)
        return rule[0]
        
    
# Stores all possible bud types of a tree
# There should be at least one bud type
# The bud with index 0 is the starting bud
class BudCollection:
    def __init__(self):
        # dict storing all bud types
        self.buds = {}
    
    # add bud type to the collection
    def add(self, index, budRules, weights):
        budType = BudType(budRules, weights)
        self.buds[index] = budType
    
    # get the bud type at given index
    def get(self, index):
        return self.buds[index]
    
# Tree parts
#---------------------------------------------------------------------------------  

# Generic tree part, storing the blender object and corresponding bone
class TreePart:
    __slots__ = ('id', 'obj', 'bone')
    
    idGen = 1
    name = "Part"
    
    def __init__(self, 
                 randomMesh, rig, parentBone,
                 boneLength = 0.2,
                 worldMatrix = Matrix.Identity(4), 
                 scaleMatrix = Matrix.Identity(4)):
        # Assign an id to the tree part
        self.id = TreePart.idGen
        TreePart.idGen += 1
        
        #Create mesh
        self.obj = randomMesh.get()
        self.obj.matrix_world = worldMatrix @ scaleMatrix
        self.obj.name = self.name + " " + str(self.id)
        
        #Create bone
        self.addBone(rig, parentBone, worldMatrix, boneLength)
        self.addVertexGroup()

    # create bone for the tree part and add to the rig   
    def addBone(self, rig, parentBone, worldMatrix, boneLength):
        # select the armature
        bpy.context.view_layer.objects.active = rig
        # go into edit mode to add bones
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        # add a bone to the armature
        bone = rig.data.edit_bones.new('bone_' + str(self.id))
        # set its location
        bone.head = worldMatrix.to_translation().freeze()
        bone.tail = (worldMatrix @ Matrix.Translation((0, 0, boneLength))).to_translation().freeze()
        
        bone.parent = parentBone
        bone.inherit_scale = 'ALIGNED'
        # bone.use_connect = True
        
        self.bone = bone
        
        # go back into object mode
        bpy.ops.object.mode_set(mode='OBJECT')
        
    def addVertexGroup(self):
        #assign vertex group weight
        group = self.obj.vertex_groups.new(name = 'bone_' + str(self.id))
        verts = []
        for v in self.obj.data.vertices:
            verts.append(v.index)
        group.add(verts, 1.0, 'ADD')
    
    
# Represents the growing part of the tree, which can either develop into a stem 
# (with new nodes and leaves attached) or into a flower.
class Bud(TreePart):
    __slots__ = (
        'potential',  # how close the bud is to sprouting
        'type',       # bud type
        'stem',       # the stem this bud is attached to 
        'apicalBud'   # the parent bud of this bud
    )
    
    name = "Bud"
    
    def __init__(self, randomMesh, rig, parentBone, budCollection, parentMatrix, 
                 budT, stem = None, apicalBud = None):
        # create the bud mesh
        TreePart.__init__(self, randomMesh, rig, parentBone)

        self.rig = rig

        # set the apical bud
        self.apicalBud = apicalBud
        
        # apply the template and set the world transformation of the mesh
        self.renew(budCollection, parentMatrix, budT, stem, parentBone)
    
    # Transform the bud after it had sprouted
    def renew(self, budCollection, parentMatrix, budT, stem):
        # set the type of the bud
        self.type = budCollection.get(budT.index)
                
        # set the parent stem
        self.stem = stem
        
        self.potential = 0
        
        # calculate the world transform of the bud from the budT angles
        divAngle = math.radians(budT.divAngleR.get())
        brcAngle = math.radians(budT.brcAngleR.get())
        rollAngle = math.radians(budT.rollAngleR.get())
        
        eul = Euler((0.0, brcAngle, divAngle), 'XYZ').to_matrix().to_4x4()
        roll = Matrix.Rotation(rollAngle, 4, 'Z')
        worldMatrix = parentMatrix @ eul @ roll
        
        self.obj.matrix_world = worldMatrix
        
        # select the armature
        bpy.context.view_layer.objects.active = rig
        # go into edit mode 
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        # set its location
        self.bone.head = worldMatrix.to_translation().freeze()
        self.bone.tail = (worldMatrix @ Matrix.Translation((0, 0, 0.2))).to_translation().freeze()
        
        self.bone.parent = stem.bone
    
        # go back into object mode
        bpy.ops.object.mode_set(mode='OBJECT')
    
    
    # Update the bud with the given potential.
    def update(self, potential):
        self.potential += potential
        if (potential > 1):
            return self.type.sprout()
        

    
        

# A woody segment of the tree between 2 consecutive nodes. Features secondary growth (widening)   
class Stem(TreePart):
    __slots__ = 'length'
    name = "Stem"
    
    def __init__(self, randomMesh, parentMatrix, length, rig, parentBone): 
        self.length = length
        scaleMatrix = Matrix.Diagonal(Vector((1.0,1.0,length,1.0)))
        TreePart.__init__(self, randomMesh, rig, parentBone, length,
                          parentMatrix, scaleMatrix)
        
        
# Tree class  
#---------------------------------------------------------------------------------  

class Tree:
    
    def __init__(self, budCollection, stemMeshR, budMeshR):
        self.stemMeshR = stemMeshR
        self.budMeshR = budMeshR
        self.budCollection = budCollection
        
        (self.rig, self.pivotBone) = self.createRig()
        
        # age of the tree in years
        self.age = 0
        # current day in the year
        self.currDay = 1
        
        # all tree parts
        self.stems = []
        
        # create starting bud
        budT = BudTemplate(index = 0, 
                           brcAngleR = RV(0.0,20.0),
                           divAngleR = RV(0.0,60.0),
                           rollAngleR = RV(0.0,180.0)
                          )
                          
        startBud = Bud(budMeshR, self.rig, budCollection, Matrix.Identity(4), budT)
        
        self.buds = [startBud]
        
        # random meshes
        self.stemMeshR = stemMeshR
        self.budMeshR = budMeshR
    
    def createRig(self):
        # the armature of the tree
        armature = bpy.data.armatures.new('TreeArmature')

        # create a rig and link it to the collection
        rig = bpy.data.objects.new('TreeRig', armature)
        bpy.context.scene.collection.objects.link(rig)
        
        # select the armature
        bpy.context.view_layer.objects.active = rig
        # go into edit mode to add bones
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        # add a bone to the armature
        pivotBone = rig.data.edit_bones.new('bone_0')
        pivotBone.tail = (0.0, 0.0, 0.0)
        pivotBone.head = (0.0, 0.0, -0.2)
        
        # go back into object mode
        bpy.ops.object.mode_set(mode='OBJECT')
        
        return (rig, pivotBone)

    
    def complete(self):
        # deselect all objects
        bpy.ops.object.select_all(action='DESELECT')

        #select all branches
        for stem in self.stems:
            stem.obj.select_set(True)
            
        for bud in self.buds:
            bud.obj.select_set(True)
            
        #set rig to be active object
        bpy.context.view_layer.objects.active = self.buds[0].obj


        #join the object together
        bpy.ops.object.join()

        treemesh = bpy.context.view_layer.objects.active

        # parent the mesh to the armature
        treemesh.parent = self.rig
        treemesh.name = "TreeMesh"

        #add armature modifier
        treemesh.modifiers.new(name = 'Armature', type = 'ARMATURE')
        treemesh.modifiers['Armature'].object = self.rig
    
    # time - number of days to simulate growth for
    def grow(self, time = 1):
        for i in range(1, ITERATIONS + 1, 1):
            print("ITERATION " + str(i))
            added = []
            
            for bud in self.buds:
                growthRule = bud.update(2)
                if growthRule is not None:
                    oldParentMatrix = bud.obj.matrix_world
                        
                    length = growthRule.stemT.lengthRatioR.get()
                    parentBone = self.pivotBone 
                       
                    if bud.stem is not None:
                        length *= bud.stem.length
                        parentBone = bud.stem.bone
                       
                    if (length < 0):
                        length = 0
                    
                    
                    stem = Stem(self.stemMeshR, oldParentMatrix, length, self.rig, parentBone)
                    self.stems.append(stem)
                    
                    parentMatrix = oldParentMatrix @ Matrix.Translation((0, 0, length))
                    
                    # renew apical bud
                    budT = growthRule.apiBudT
                    bud.renew(budCollection, 
                              self.rig,
                              parentMatrix, 
                              budT,
                              stem
                              )
                    
                    for axiBudT in growthRule.axiBudTs:
                        axiBud = Bud(budMeshR,
                                     budCollection,
                                     self.rig,
                                     parentMatrix,
                                     axiBudT,
                                     stem,
                                     bud
                                     )
                        added.append(axiBud)
            
            self.buds.extend(added)
        
        
stemMeshR = RandomMesh(['stem'])
budMeshR = RandomMesh(['bud'])

budCollection = BudCollection()
budT = BudTemplate(index = 0, 
                    brcAngleR = RV(0.0,3.0),
                    divAngleR = RV(0.0,1.0),
                    rollAngleR = RV(180.0,30.0)
                    )
                    
budT1 = BudTemplate(index = 0, 
                    brcAngleR = RV(60.0,2.0),
                    divAngleR = RV(180.0,30.0),
                    rollAngleR = RV(0.0,1.0)
                    )
                    
budCollection.add(0, [BudRule(StemTemplate(RV(0.7,0.05)), budT, [budT1, budT1, budT1])], [1.0])

tree = Tree(budCollection, stemMeshR, budMeshR)
tree.grow()
tree.complete()